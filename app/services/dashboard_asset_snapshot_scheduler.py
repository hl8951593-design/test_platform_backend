import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.dashboard_asset_snapshot_service import DashboardAssetSnapshotService


logger = logging.getLogger(__name__)


class DashboardAssetSnapshotScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.DASHBOARD_ASSET_SNAPSHOT_SCHEDULER_ENABLED or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="dashboard-asset-snapshot-scheduler",
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
                count = DashboardAssetSnapshotService(db).capture_all()
                db.commit()
                return count
            except Exception:
                db.rollback()
                raise

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                captured = self.tick()
                if captured:
                    logger.info("Captured %s dashboard asset snapshot scopes", captured)
            except SQLAlchemyError:
                logger.exception("Dashboard asset snapshot scheduler database error")
            except Exception:  # noqa: BLE001
                logger.exception("Dashboard asset snapshot scheduler error")
            self._stop_event.wait(
                max(settings.DASHBOARD_ASSET_SNAPSHOT_SCHEDULER_INTERVAL_SECONDS, 60)
            )


dashboard_asset_snapshot_scheduler = DashboardAssetSnapshotScheduler()
