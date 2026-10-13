"""Editable compound assignments and draggable plot annotation placement."""

from copy import deepcopy

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chromakit.annotations.labels import make_label, reviewed_labels
from chromakit.ui.peak_panel import spin


class MovableLabel(pg.TextItem):
    moved = Signal(float, float)

    def __init__(self, text):
        super().__init__(text=text, color="#334A54", anchor=(0.5, 1))
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable, True)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.moved.emit(self.pos().x(), self.pos().y())


class LabelPanel(QWidget):
    changed = Signal()

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.undo_history = []
        self.redo_history = []
        self.candidates = []
        layout = QVBoxLayout(self)
        heading = QLabel("COMPOUND LABELS")
        heading.setObjectName("section")
        layout.addWidget(heading)
        note = QLabel(
            "Choose a measured peak or fitted component. Assign a name and review status; "
            "drag labels on the plot after adding them. Reprocessing flags assignments for review."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.target = QComboBox()
        form.addRow("Peak/component", self.target)
        self.name = QTextEdit()
        self.name.setMaximumHeight(85)
        form.addRow("Compound name", self.name)
        self.status = QComboBox()
        self.status.addItems(["Tentative", "Confirmed"])
        form.addRow("Assignment", self.status)
        self.rotation = spin(-180, 180, 0)
        form.addRow("Rotation (degrees)", self.rotation)
        layout.addLayout(form)
        self.add = QPushButton("Assign label to selected peak")
        self.add.clicked.connect(self.assign)
        layout.addWidget(self.add)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Status", "Review"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self.selected)
        layout.addWidget(self.table, 1)
        update = QPushButton("Update selected label")
        update.clicked.connect(self.update)
        layout.addWidget(update)
        rebind = QPushButton("Rebind selected label to chosen peak")
        rebind.clicked.connect(lambda: self.assign(rebind=True))
        layout.addWidget(rebind)
        remove = QPushButton("Remove selected label")
        remove.clicked.connect(self.remove)
        layout.addWidget(remove)
        undo = QPushButton("Undo label change")
        undo.clicked.connect(self.history_action)
        layout.addWidget(undo)
        redo = QPushButton("Redo label change")
        redo.clicked.connect(lambda: self.history_action(True))
        layout.addWidget(redo)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def entries(self):
        trace = self.window.trace
        return (
            self.window.project_extras.setdefault("labels", {}).setdefault(trace.id, [])
            if trace
            else []
        )

    def save_history(self):
        self.undo_history.append(deepcopy(self.window.project_extras.get("labels", {})))
        self.redo_history.clear()
        self.window.project_extras["labels_undo"] = self.undo_history
        self.window.project_extras["labels_redo"] = self.redo_history

    def refresh(self):
        self.candidates = []
        trace = self.window.trace
        labels = []
        if trace:
            i = self.window.samples.currentRow()
            baseline = self.window.baseline_states[i].applied
            measured = self.window.peak_states[i]
            fitted = self.window.fit_states[i]
            if measured.current:
                self.candidates.extend(
                    ("Measured peaks", measured.result, p) for p in measured.result.peaks
                )
            if fitted.valid(fitted.result):
                self.candidates.extend(
                    ("Fitted components", fitted.result, p) for p in fitted.result.peaks
                )
            labels = reviewed_labels(
                self.entries(),
                measured.result,
                fitted.result,
                baseline,
                self.window.project_extras.get("compound_library", []),
            )
        old = self.target.currentText()
        self.target.clear()
        self.target.addItems(
            [
                f"{origin} · {peak.id} · {peak.retention_time:.6g}"
                for origin, _, peak in self.candidates
            ]
        )
        index = self.target.findText(old)
        if index >= 0:
            self.target.setCurrentIndex(index)
        self.add.setEnabled(bool(self.candidates))
        self.table.setRowCount(len(labels))
        for i, label in enumerate(labels):
            for j, value in enumerate(
                [
                    label["name"],
                    label["status"],
                    "STALE — rebind after review" if label["stale"] else "Current",
                ]
            ):
                self.table.setItem(i, j, QTableWidgetItem(value))

    def selected(self, row, _column):
        if row >= len(self.entries()):
            return
        entry = self.entries()[row]
        self.name.setPlainText(entry["name"])
        self.status.setCurrentText(entry["status"])
        self.rotation.setValue(entry.get("rotation", 0))

    def assign(self, _checked=False, rebind=False):
        row = self.target.currentIndex()
        if not 0 <= row < len(self.candidates):
            return
        origin, result, peak = self.candidates[row]
        i = self.window.samples.currentRow()
        try:
            label = make_label(
                self.window.trace,
                self.window.baseline_states[i].applied,
                result,
                peak,
                self.name.toPlainText(),
                self.status.currentText(),
                origin,
            )
        except ValueError as error:
            self.message.setText(str(error))
            return
        label["rotation"] = self.rotation.value()
        selected = self.table.currentRow()
        if rebind and not 0 <= selected < len(self.entries()):
            return
        self.save_history()
        if rebind:
            self.entries()[selected] = label
        else:
            self.entries().append(label)
        self.refresh()
        self.changed.emit()

    def update(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries()) and self.name.toPlainText().strip():
            self.save_history()
            self.entries()[row].update(
                name=self.name.toPlainText().strip(),
                status=self.status.currentText(),
                rotation=self.rotation.value(),
            )
            self.window.project_extras["labels_undo"] = self.undo_history
            self.window.project_extras["labels_redo"] = self.redo_history
            self.refresh()
            self.changed.emit()

    def remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries()):
            self.save_history()
            self.entries().pop(row)
            self.window.project_extras["labels_undo"] = self.undo_history
            self.window.project_extras["labels_redo"] = self.redo_history
            self.refresh()
            self.changed.emit()

    def move(self, identifier, x, y, raw=False):
        label = next((label for label in self.entries() if label["id"] == identifier), None)
        if label:
            self.save_history()
            label["label_x"] = x
            label["label_y_raw" if raw else "label_y"] = y
            self.changed.emit()

    def history_action(self, redo=False):
        source, destination = (
            (self.redo_history, self.undo_history)
            if redo
            else (self.undo_history, self.redo_history)
        )
        if source:
            destination.append(deepcopy(self.window.project_extras.get("labels", {})))
            self.window.project_extras["labels"] = source.pop()
            self.window.project_extras["labels_undo"] = self.undo_history
            self.window.project_extras["labels_redo"] = self.redo_history
            self.refresh()
            self.changed.emit()
