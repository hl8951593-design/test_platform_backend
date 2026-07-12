from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.models.execution_diagnostic import (
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
