"""Bounded shared inference scheduler for all cameras."""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(order=True)
class InferenceJob:
    priority: int
    sequence: int
    created_at: float = field(compare=False)
    frame: Any = field(compare=False)
    kwargs: dict[str, Any] = field(compare=False)
    future: Future = field(compare=False)


class InferenceScheduler:
    def __init__(self, handler: Callable[..., Any], max_queue: int = 2) -> None:
        self.handler = handler
        self.jobs: queue.PriorityQueue[InferenceJob] = queue.PriorityQueue(maxsize=max_queue)
        self._sequence = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.processed = 0
        self.dropped = 0
        self.thread = threading.Thread(target=self._run, name="shared-inference-worker", daemon=True)
        self.thread.start()

    def submit(self, frame: Any, priority: int = 10, **kwargs: Any) -> Future:
        future: Future = Future()
        with self._lock:
            self._sequence += 1
            job = InferenceJob(priority, self._sequence, time.monotonic(), frame, kwargs, future)
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.dropped += 1
            future.set_exception(RuntimeError("stale inference frame dropped"))
        return future

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if job.future.cancelled() or time.monotonic() - job.created_at > 2.0:
                self.dropped += 1
                if not job.future.done():
                    job.future.set_exception(RuntimeError("stale inference frame dropped"))
                continue
            try:
                job.future.set_result(self.handler(job.frame, **job.kwargs))
                self.processed += 1
            except Exception as exc:  # noqa: BLE001
                if not job.future.done():
                    job.future.set_exception(exc)

    def close(self) -> None:
        self._stop.set()
        self.thread.join(timeout=3)
