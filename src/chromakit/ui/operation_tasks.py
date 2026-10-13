"""Shared cancellable scheduler for export, image and batch operations."""

import logging

from chromakit.analysis.peaks import PeakCancelled, PeakProblem
from chromakit.importers.text import ImportCancelled, ImportProblem
from chromakit.ui.peak_tasks import PeakController, PeakTask


class OperationTask(PeakTask):
    def run(self):
        try:
            result = self.operation(self.cancelled.is_set)
        except (ImportCancelled, PeakCancelled):
            return
        except (ImportProblem, PeakProblem, OSError, ValueError) as error:
            self.failed.emit(self.generation, str(error))
        except Exception:
            logging.getLogger(__name__).exception("Operation failed")
            self.failed.emit(self.generation, "Operation failed; see terminal diagnostics.")
        else:
            if not self.cancelled.is_set():
                self.succeeded.emit(self.generation, result)


class OperationController(PeakController):
    def create_task(self, generation, operation, unused):
        return OperationTask(generation, operation, self)
