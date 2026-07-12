import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.response import normalize_response_data  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.scenario import TestScenarioRun  # noqa: E402
from app.models.test_case import TestCaseExecution  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.visual_flow import VisualFlowExecution  # noqa: E402
from app.models.websocket_test_case import WebSocketTestCaseExecution  # noqa: E402
from app.services.execution_diagnostic_persistence import (  # noqa: E402
    ExecutionDiagnosticPersistence,
)
from app.services.execution_record_service import ExecutionRecordService  # noqa: E402


_SOURCE_MODELS = {
    "http": TestCaseExecution,
    "websocket": WebSocketTestCaseExecution,
    "scenario": TestScenarioRun,
    "flow": VisualFlowExecution,
}


class ExecutionDiagnosticBackfillSourceReader:
    def __init__(self, db: Session):
        self.db = db
        self.record_service = ExecutionRecordService(db)
        self.system_user = User(
            id=0,
            username="execution-diagnostic-backfill",
            account="execution-diagnostic-backfill",
            password_hash="!",
            phone="backfill",
            email="backfill@localhost",
            is_active=True,
            is_admin=True,
        )

    def read_batch(
        self,
        *,
        project_id: int,
        execution_type: str,
        after_id: int,
        limit: int,
        restore_legacy_snapshots: bool,
    ) -> list[tuple[int, dict[str, Any]]]:
        model = _SOURCE_MODELS[execution_type]
        ids = self.db.scalars(
            select(model.id)
            .where(model.project_id == project_id, model.id > after_id)
            .order_by(model.id.asc())
            .limit(limit)
        ).all()
        results: list[tuple[int, dict[str, Any]]] = []
        for execution_id in ids:
            detail = self.record_service.get_detail(
                project_id=project_id,
                execution_type=execution_type,
                execution_id=int(execution_id),
                current_user=self.system_user,
            )
            results.append((int(execution_id), normalize_response_data(detail)))
        return results


class ExecutionDiagnosticBackfillRunner:
    def __init__(
        self,
        *,
        db: Session,
        source_reader: Any | None = None,
        persistence: ExecutionDiagnosticPersistence | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        self.db = db
        self.source_reader = source_reader or ExecutionDiagnosticBackfillSourceReader(db)
        self.persistence = persistence or ExecutionDiagnosticPersistence(db)
        self.progress = progress

    def run(
        self,
        *,
        project_id: int,
        execution_type: str,
        after_id: int,
        batch_size: int,
        dry_run: bool,
        restore_legacy_snapshots: bool,
    ) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        checkpoint = after_id
        while True:
            rows = self.source_reader.read_batch(
                project_id=project_id,
                execution_type=execution_type,
                after_id=checkpoint,
                limit=batch_size,
                restore_legacy_snapshots=restore_legacy_snapshots,
            )
            if not rows:
                break
            for execution_id, execution in rows:
                self.persistence.stage_execution(
                    project_id=project_id,
                    execution_type=execution_type,
                    execution_id=execution_id,
                    execution=execution,
                )
                checkpoint = execution_id
            if dry_run:
                self.db.rollback()
            else:
                self.db.commit()
                if self.progress is not None:
                    self.progress(f"last_committed_id={checkpoint}")
        return checkpoint


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill bounded execution diagnostic read models."
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument(
        "--execution-type",
        choices=tuple(_SOURCE_MODELS),
        required=True,
    )
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore-legacy-snapshots", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with SessionLocal() as db:
        runner = ExecutionDiagnosticBackfillRunner(db=db, progress=print)
        try:
            checkpoint = runner.run(
                project_id=args.project_id,
                execution_type=args.execution_type,
                after_id=args.after_id,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                restore_legacy_snapshots=args.restore_legacy_snapshots,
            )
        except Exception:
            db.rollback()
            raise
    label = "last_processed_id" if args.dry_run else "last_committed_id"
    print(f"{label}={checkpoint}")


if __name__ == "__main__":
    main()
