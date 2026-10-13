"""Cooperative background tasks; widgets only receive results on the GUI thread."""

from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QThread, Signal

from chromakit.importers.text import ImportCancelled, ImportProblem


class ImportTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancelled = Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            result = self.operation(self.cancelled.is_set)
        except ImportCancelled:
            return
        except (ImportProblem, OSError) as error:
            self.failed.emit(str(error))
        else:
            if not self.cancelled.is_set():
                self.succeeded.emit(result)
