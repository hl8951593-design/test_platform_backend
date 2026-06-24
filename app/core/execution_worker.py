import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Callable, TypeVar

from app.core.config import settings


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
        if not self._capacity.acquire(blocking=False):
            return None
        future = self._executor.submit(fn, *args, **kwargs)
        future.add_done_callback(self._release_and_log)
        return future

    def _release_and_log(self, future) -> None:
        self._capacity.release()
        try:
            future.result()
        except Exception:  # noqa: BLE001
            logger.exception("Execution worker task failed")


execution_worker = ExecutionWorker(
    max_workers=settings.EXECUTION_WORKER_MAX_WORKERS,
    queue_size=settings.EXECUTION_WORKER_QUEUE_SIZE,
)
