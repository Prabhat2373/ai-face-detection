"""Run blocking work without freezing the Qt UI thread."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


_ACTIVE_WORKERS: set["Worker"] = set()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[[], Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()


def run_in_background(
    function: Callable[[], Any],
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    on_finished: Callable[[], None] | None = None,
) -> Worker:
    worker = Worker(function)
    if on_result:
        worker.signals.result.connect(on_result)
    if on_error:
        worker.signals.error.connect(on_error)
    def release_worker() -> None:
        _ACTIVE_WORKERS.discard(worker)
        if on_finished:
            on_finished()

    worker.signals.finished.connect(release_worker)
    _ACTIVE_WORKERS.add(worker)
    QThreadPool.globalInstance().start(worker)
    return worker
