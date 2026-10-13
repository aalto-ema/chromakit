"""Per-trace fit drafts, accepted results, and baseline dependency history."""

from dataclasses import dataclass, field

from chromakit.analysis.deconvolution import FitRecipe, FitResult
from chromakit.analysis.peaks import baseline_key
from chromakit.application.baselines import BaselineState


@dataclass
class FitState:
    baseline_state: BaselineState
    recipe: FitRecipe | None = None
    preview: FitResult | None = None
    result: FitResult | None = None
    undo_history: list[FitResult | None] = field(default_factory=list)
    redo_history: list[FitResult | None] = field(default_factory=list)

    def valid(self, result):
        applied = self.baseline_state.applied
        return bool(result and applied and result.baseline_key == baseline_key(applied))

    def accept(self):
        if (
            not self.valid(self.preview)
            or self.preview.recipe != self.recipe
            or self.preview is self.result
        ):
            return False
        self.undo_history.append(self.result)
        self.redo_history.clear()
        self.result = self.preview
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
            self.preview = self.result
            self.recipe = self.result.recipe if self.result else None
