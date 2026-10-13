"""One cancellable baseline worker at a time, with generation-checked delivery."""

import logging
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal

from chromakit.analysis.baseline import BaselineCancelled, BaselineProblem, estimate_baseline

logger = logging.getLogger(__name__)


class BaselineTask(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int)

    def __init__(self, generation, trace, recipe, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.trace = trace
        self.recipe = recipe
        self.cancelled = Event()

    def run(self):
        try:
            result = estimate_baseline(
                self.trace,
                self.recipe,
                self.cancelled.is_set,
                lambda step, total: self.progress.emit(self.generation, step, total),
            )
        except BaselineCancelled:
            return
        except BaselineProblem as error:
            self.failed.emit(self.generation, str(error))
        except Exception:
            # Worker boundary: never leave the GUI indefinitely busy on an
            # unexpected library failure. Preserve a diagnostic traceback.
            logger.exception("Baseline computation failed")
            self.failed.emit(
                self.generation, "Baseline calculation failed; see terminal diagnostics."
            )
        else:
            if not self.cancelled.is_set():
                self.succeeded.emit(self.generation, result)


class BaselineController(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0
        self.task: BaselineTask | None = None
        self.pending = None
        self.closed = False

    def cancel(self):
        self.generation += 1
        self.pending = None
        if self.task:
            self.task.cancelled.set()

    def request(self, trace, recipe):
        self.cancel()
        self.pending = (self.generation, trace, recipe)
        if self.task is None:
            self._start_pending()

    def _start_pending(self):
        if self.closed or self.pending is None:
            return
        generation, trace, recipe = self.pending
        self.pending = None
        task = self.create_task(generation, trace, recipe)
        self.task = task
        task.succeeded.connect(self._succeeded)
        task.failed.connect(self._failed)
        task.progress.connect(self._progress)
        task.finished.connect(self._finished)
        task.start()

    def create_task(self, generation, trace, recipe):
        return BaselineTask(generation, trace, recipe, self)

    def _succeeded(self, generation, result):
        if not self.closed and generation == self.generation:
            self.succeeded.emit(result)

    def _failed(self, generation, message):
        if not self.closed and generation == self.generation:
            self.failed.emit(message)

    def _progress(self, generation, step, total):
        if not self.closed and generation == self.generation:
            self.progress.emit(step, total)

    def _finished(self):
        completed = self.task
        self.task = None
        if completed is not None:
            completed.deleteLater()
        self._start_pending()

    def shutdown(self):
        self.closed = True
        self.cancel()
        if self.task is not None:
            self.task.wait()
