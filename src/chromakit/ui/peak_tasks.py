"""Peak jobs reuse the cancellable, generation-checked single-worker scheduler."""

import logging
from threading import Event

from PySide6.QtCore import QThread, Signal

from chromakit.analysis.peaks import PeakCancelled, PeakProblem
from chromakit.ui.baseline_tasks import BaselineController


class PeakTask(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int)

    def __init__(self, generation, operation, parent):
        super().__init__(parent)
        self.calculation_label = "Peak"
        self.generation = generation
        self.operation = operation
        self.cancelled = Event()

    def run(self):
        try:
            result = self.operation(self.cancelled.is_set)
        except PeakCancelled:
            return
        except PeakProblem as error:
            self.failed.emit(self.generation, str(error))
        except Exception:
            logging.getLogger(__name__).exception("%s calculation failed", self.calculation_label)
            self.failed.emit(
                self.generation,
                f"{self.calculation_label} calculation failed; see terminal diagnostics.",
            )
        else:
            if not self.cancelled.is_set():
                self.succeeded.emit(self.generation, result)


class PeakController(BaselineController):
    def request_operation(self, operation):
        super().request(operation, None)

    def create_task(self, generation, operation, unused):
        return PeakTask(generation, operation, self)
