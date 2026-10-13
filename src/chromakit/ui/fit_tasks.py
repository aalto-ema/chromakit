"""Generation-guarded fit workers stream provisional curves without UI mutations."""

from PySide6.QtCore import Signal

from chromakit.ui.peak_tasks import PeakController, PeakTask


class FitTask(PeakTask):
    live = Signal(int, object)

    def __init__(self, generation, operation, parent):
        super().__init__(generation, lambda cancel: operation(cancel, self.publish), parent)
        self.calculation_label = "Fit"

    def publish(self, snapshot):
        if not self.cancelled.is_set():
            self.live.emit(self.generation, snapshot)


class FitController(PeakController):
    live = Signal(object)

    def create_task(self, generation, operation, unused):
        task = FitTask(generation, operation, self)
        task.live.connect(self.forward_live)
        return task

    def forward_live(self, generation, snapshot):
        if generation == self.generation and not self.closed:
            self.live.emit(snapshot)
