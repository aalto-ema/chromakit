"""Per-trace applied baseline history; drafts never overwrite accepted results."""

from dataclasses import dataclass, field

from chromakit.analysis.baseline import BaselineRecipe, BaselineResult, input_key
from chromakit.domain import Trace


@dataclass
class BaselineState:
    trace: Trace
    draft: BaselineRecipe = field(default_factory=BaselineRecipe)
    applied: BaselineResult | None = None
    preview: BaselineResult | None = None
    undo_history: list[BaselineResult | None] = field(default_factory=list)
    redo_history: list[BaselineResult | None] = field(default_factory=list)

    def update_draft(self, recipe: BaselineRecipe):
        self.draft = recipe
        self.preview = None

    def accept_preview(self, result: BaselineResult) -> bool:
        if result.input_key != input_key(self.trace) or result.recipe != self.draft:
            return False
        self.preview = result
        return True

    def apply(self) -> bool:
        if self.preview is None or self.preview.recipe != self.draft:
            return False
        if self.applied is not None and self.applied.recipe == self.preview.recipe:
            return False
        self.undo_history.append(self.applied)
        self.redo_history.clear()
        self.applied = self.preview
        return True

    def discard(self):
        self.draft = self.applied.recipe if self.applied else BaselineRecipe()
        self.preview = self.applied

    def clear(self):
        if self.applied is not None:
            self.undo_history.append(self.applied)
            self.redo_history.clear()
        self.applied = None
        self.preview = None
        self.draft = BaselineRecipe()

    def undo(self):
        if self.undo_history:
            self.redo_history.append(self.applied)
            self.applied = self.undo_history.pop()
            self.discard()

    def redo(self):
        if self.redo_history:
            self.undo_history.append(self.applied)
            self.applied = self.redo_history.pop()
            self.discard()
