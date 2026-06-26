import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.core.config import settings
from app.core.logging import reset_request_id, set_request_id


logger = logging.getLogger("app.request")


def register_request_logging_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                _log_request(request, response.status_code, duration_ms)
            reset_request_id(token)


def _log_request(request: Request, status_code: int, duration_ms: int) -> None:
    if not _should_log(status_code, duration_ms):
        return
    log_method = logger.info
    if status_code >= 500:
        log_method = logger.error
    elif status_code >= 400:
        log_method = logger.warning
    log_method(
        "request_completed method=%s path=%s query=%s status=%s duration_ms=%s client=%s",
        request.method,
        request.url.path,
        str(request.url.query or ""),
        status_code,
        duration_ms,
        request.client.host if request.client else "-",
    )


def _should_log(status_code: int, duration_ms: int) -> bool:
    if status_code >= 400:
        return True
    if settings.LOG_REQUESTS:
        return True
    return duration_ms >= settings.LOG_SLOW_REQUEST_MS
