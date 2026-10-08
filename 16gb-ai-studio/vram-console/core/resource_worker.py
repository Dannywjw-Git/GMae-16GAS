"""Bounded command execution; HTTP handlers never perform GPU adapter calls."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Callable, TypeVar
from core.resource_coordinator import ResourceDenied

T = TypeVar("T")


class ResourceCommandWorker:
    """One command worker with bounded pending work and explicit lifecycle."""

    def __init__(self, capacity: int = 8):
        self._slots = threading.BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu-command")

    def submit(self, action: Callable[[], T]) -> Future[T]:
        """Queue an intent; reject overload without executing or cancelling other work."""
        if not self._slots.acquire(blocking=False):
            raise ResourceDenied("COMMAND_QUEUE_FULL", "资源命令队列已满，请稍后重试")
        try:
            future = self._executor.submit(action)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        return future

    def shutdown(self) -> None:
        """Wait for submitted work; never silently cancel an in-flight GPU action."""
        self._executor.shutdown(wait=True)
