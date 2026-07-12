import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.execution_metrics_service import ExecutionMetricsService


logger = logging.getLogger(__name__)


class ExecutionMetricsScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if (
            not settings.EXECUTION_METRICS_SCHEDULER_ENABLED
            or self._thread is not None
        ):
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="execution-metrics-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def tick(self) -> int:
        with SessionLocal() as db:
            try:
                rebuilt = ExecutionMetricsService(db).rebuild_recent()
                db.commit()
                return rebuilt
            except Exception:
                db.rollback()
                raise

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                rebuilt = self.tick()
                if rebuilt:
                    logger.info("Rebuilt %s execution metric hour buckets", rebuilt)
            except SQLAlchemyError:
                logger.exception("Execution metrics scheduler database error")
            except Exception:  # noqa: BLE001
                logger.exception("Execution metrics scheduler error")
            self._stop_event.wait(
                max(settings.EXECUTION_METRICS_SCHEDULER_INTERVAL_SECONDS, 10)
            )


execution_metrics_scheduler = ExecutionMetricsScheduler()
