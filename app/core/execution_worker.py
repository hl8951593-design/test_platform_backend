import logging
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Callable, TypeVar

from app.core.config import settings
from app.core.logging import get_request_id, reset_request_id, set_request_id


logger = logging.getLogger(__name__)
T = TypeVar("T")


class ExecutionWorker:
    def __init__(self, *, max_workers: int, queue_size: int) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="execution-worker",
        )
        self._capacity = BoundedSemaphore(max_workers + queue_size)

    def submit(self, fn: Callable[..., T], *args, **kwargs) -> bool:
        return self.submit_future(fn, *args, **kwargs) is not None

    def submit_future(self, fn: Callable[..., T], *args, **kwargs) -> Future[T] | None:
        request_id = get_request_id()
        task_id = str(uuid.uuid4())
        fn_name = _callable_name(fn)
        if not self._capacity.acquire(blocking=False):
            logger.warning(
                "Execution worker queue full task_id=%s request_id=%s fn=%s",
                task_id,
                request_id,
                fn_name,
            )
            return None
        logger.info(
            "Execution worker task accepted task_id=%s request_id=%s fn=%s",
            task_id,
            request_id,
            fn_name,
        )
        future = self._executor.submit(
            self._run_task,
            task_id,
            request_id,
            fn_name,
            fn,
            args,
            kwargs,
        )
        future.add_done_callback(self._release_capacity)
        return future

    def _run_task(
        self,
        task_id: str,
        request_id: str,
        fn_name: str,
        fn: Callable[..., T],
        args: tuple,
        kwargs: dict,
    ) -> T:
        token = set_request_id(request_id)
        started = time.perf_counter()
        logger.info(
            "Execution worker task started task_id=%s request_id=%s fn=%s",
            task_id,
            request_id,
            fn_name,
        )
        try:
            try:
                result = fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - started) * 1000)
                logger.exception(
                    "Execution worker task failed task_id=%s request_id=%s fn=%s duration_ms=%s",
                    task_id,
                    request_id,
                    fn_name,
                    duration_ms,
                )
                raise
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Execution worker task completed task_id=%s request_id=%s fn=%s duration_ms=%s",
                task_id,
                request_id,
                fn_name,
                duration_ms,
            )
            return result
        finally:
            reset_request_id(token)

    def _release_capacity(self, future) -> None:
        self._capacity.release()


def _callable_name(fn: Callable[..., object]) -> str:
    return getattr(fn, "__qualname__", getattr(fn, "__name__", type(fn).__name__))


execution_worker = ExecutionWorker(
    max_workers=settings.EXECUTION_WORKER_MAX_WORKERS,
    queue_size=settings.EXECUTION_WORKER_QUEUE_SIZE,
)
