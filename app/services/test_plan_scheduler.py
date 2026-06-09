import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.test_plan_service import TestPlanService


logger = logging.getLogger(__name__)


class TestPlanScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.TEST_PLAN_SCHEDULER_ENABLED or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="test-plan-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def tick(self) -> int:
        with SessionLocal() as db:
            return TestPlanService(db).run_due_plans()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                executed = self.tick()
                if executed:
                    logger.info("Executed %s scheduled test plan runs", executed)
            except SQLAlchemyError:
                logger.exception("Test plan scheduler database error")
            except Exception:  # noqa: BLE001
                logger.exception("Test plan scheduler error")
            self._stop_event.wait(max(settings.TEST_PLAN_SCHEDULER_INTERVAL_SECONDS, 5))


test_plan_scheduler = TestPlanScheduler()
