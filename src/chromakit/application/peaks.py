"""Per-trace peak history and applied-baseline dependency tracking."""

from dataclasses import dataclass, field

from chromakit.analysis.peaks import PeakRecipe, PeakResult, baseline_key
from chromakit.application.baselines import BaselineState


@dataclass
class PeakState:
    baseline_state: BaselineState
    recipe: PeakRecipe = field(default_factory=PeakRecipe)
    result: PeakResult | None = None
    undo_history: list[PeakResult | None] = field(default_factory=list)
    redo_history: list[PeakResult | None] = field(default_factory=list)
    selected_id: str | None = None
    _baseline: object = None
    current_key: str | None = None

    def sync_baseline(self):
        applied = self.baseline_state.applied
        if applied is self._baseline:
            return False
        self._baseline = applied
        self.current_key = baseline_key(applied) if applied else None
        return True

    @property
    def current(self):
        return self.result is not None and self.current_key == self.result.baseline_key

    def accept(self, result):
        self.sync_baseline()
        if result.baseline_key != self.current_key:
            return False
        self.undo_history.append(self.result)
        self.redo_history.clear()
        self.result = result
        if self.selected_id not in {peak.id for peak in result.peaks}:
            self.selected_id = result.peaks[0].id if result.peaks else None
        return True

    def undo(self, redo=False):
        source, destination = (
            (self.redo_history, self.undo_history)
            if redo
            else (self.undo_history, self.redo_history)
        )
        if source:
            destination.append(self.result)
            self.result = source.pop()
