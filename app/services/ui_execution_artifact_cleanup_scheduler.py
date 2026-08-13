from __future__ import annotations

import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.ui_execution_artifact_service import UiExecutionArtifactService


logger = logging.getLogger(__name__)


class UiExecutionArtifactCleanupScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.UI_ARTIFACT_CLEANUP_ENABLED or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ui-artifact-cleanup-scheduler",
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
                return UiExecutionArtifactService(db).cleanup_expired_uploads()
            except Exception:
                db.rollback()
                raise

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                cleaned = self.tick()
                if cleaned:
                    logger.info("Cleaned %s expired UI artifact uploads", cleaned)
            except SQLAlchemyError:
                logger.exception("UI artifact cleanup database error")
            except Exception:  # noqa: BLE001
                logger.exception("UI artifact cleanup error")
            self._stop_event.wait(
                max(settings.UI_ARTIFACT_CLEANUP_INTERVAL_SECONDS, 30)
            )


ui_execution_artifact_cleanup_scheduler = UiExecutionArtifactCleanupScheduler()
