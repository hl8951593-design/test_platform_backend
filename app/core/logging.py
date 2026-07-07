import logging
import time
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
WINDOWS_LOG_ROLLOVER_LOCK_ERRORS = {32, 33}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """Rotating handler that keeps logging when Windows blocks file renames."""

    def __init__(
        self,
        *args,
        rollover_defer_seconds: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.rollover_defer_seconds = rollover_defer_seconds
        self._rollover_deferred_until = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if self._rollover_deferred_until:
            if time.monotonic() < self._rollover_deferred_until:
                return False
            self._rollover_deferred_until = 0.0
        return super().shouldRollover(record)

    def doRollover(self) -> None:
        try:
            super().doRollover()
            self._rollover_deferred_until = 0.0
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in WINDOWS_LOG_ROLLOVER_LOCK_ERRORS:
                raise
            self._rollover_deferred_until = (
                time.monotonic() + self.rollover_defer_seconds
            )
            if self.stream is None and not self.delay:
                self.stream = self._open()


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_test_platform_configured", False):
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(request_id)s] %(name)s - %(message)s"
    )
    request_filter = RequestIdFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(request_filter)
    root_logger.addHandler(stream_handler)

    if settings.LOG_FILE_PATH:
        log_path = Path(settings.LOG_FILE_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = WindowsSafeRotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_filter)
        root_logger.addHandler(file_handler)

    root_logger._test_platform_configured = True


def set_request_id(request_id: str):
    return request_id_var.set(request_id)


def reset_request_id(token) -> None:
    request_id_var.reset(token)


def get_request_id() -> str:
    return request_id_var.get()
