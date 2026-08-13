from __future__ import annotations

import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.ui_execution_runtime_service import UiExecutionRuntimeService


logger = logging.getLogger(__name__)


class UiExecutionLeaseScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.UI_EXECUTION_LEASE_SWEEP_ENABLED or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ui-execution-lease-scheduler",
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
                return UiExecutionRuntimeService(db).expire_stale_leases()
            except Exception:
                db.rollback()
                raise

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                expired = self.tick()
                if expired:
                    logger.info("Expired %s stale UI execution leases", expired)
            except SQLAlchemyError:
                logger.exception("UI execution lease scheduler database error")
            except Exception:  # noqa: BLE001
                logger.exception("UI execution lease scheduler error")
            self._stop_event.wait(
                max(settings.UI_EXECUTION_LEASE_SWEEP_INTERVAL_SECONDS, 5)
            )


ui_execution_lease_scheduler = UiExecutionLeaseScheduler()
